"""Case engine for MF-V1-COMFY correction round C — the durable resolve matrix.

This module is NOT a test module. It builds disposable fixtures, drives the
adapter over the fake transport and returns RAW COUNTS per case:

    POST (transport.submit_calls) / published artifacts / isolated staging /
    markers on disk / completion receipts / quarantine records

`tests/test_durable_resolve_c.py` asserts one matrix row per case, and
`COMFY/raw/run_matrix_c.py` dumps the same cases to JSON as the round's
evidence — including the negative control against the pre-fix bytes, because
the engine deliberately touches only long-standing API surface (it never
imports a name that exists only after the fix).

Rows (frozen matrix, one per case, see REPORT.md):

    C01  c01_unchanged_unresolved_replay
    C02  c02_receipt_replay_*            (success/failure/cancel/unknown/rejected/old-epoch)
    C03  c03_body_only_mutations         (+ c03_honest_pin_mismatch_is_isolated_staging)
    C04  c04_claimant_conflicts
    C05  c05_missing_or_corrupt
    C06  c06_legacy_rows_retained
    C07  c07_independent_new_work
    C08  c08_legacy_rows_replayed        (pytest node ids of the F01/F03/lease rows)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

COMFY_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(COMFY_ROOT), str(COMFY_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fake_transport import (history_success, light_graph, make_rig, make_spec,  # noqa: E402
                            queue_item)
from mf_comfy.adapter import ComfyStageAdapter  # noqa: E402
from mf_comfy.lease import submit_provably_never_started  # noqa: E402

SCRATCH = Path(os.environ.get("TEMP") or "C:/Users/Admin/AppData/Local/Temp") / (
    f"mfcomfy_c_{os.getpid()}")

REFUSE_CODES = {"MF_COMFY_CORRUPT_RESERVATION", "MF_COMFY_RESERVATION_CONFLICT",
                "MF_COMFY_ATTEMPT_ALREADY_TERMINAL"}
AT_TERMINAL = "MF_COMFY_ATTEMPT_ALREADY_TERMINAL"


# --------------------------------------------------------------------- fixtures
def reset_scratch() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)


def two_terminal_graph(seed: int = 42) -> dict:
    """A graph with TWO SaveImage nodes, so a contract can be re-pointed 9 -> 10."""
    graph = light_graph(seed=seed)
    graph["10"] = {"class_type": "SaveImage",
                   "inputs": {"filename_prefix": "fake_out_b", "images": ["8", 0]}}
    return graph


def base_spec(**kw):
    kw.setdefault("attempt_id", "att")
    kw.setdefault("stage_id", "stage")
    kw.setdefault("workflow_id", "wf")
    kw.setdefault("owner", "owner")
    kw.setdefault("graph", two_terminal_graph())
    kw.setdefault("stage_timeout_s", 1.0)
    kw.setdefault("terminal_outputs", {"9": {"kind": "images", "media_type": "image"}})
    return make_spec(**kw)


class Fixture:
    def __init__(self, label, root, rig, marker_path):
        self.label = label
        self.root = root
        self.rig = rig
        self.marker_path = marker_path
        self.store = rig.adapter.reservations

    # -- durability helpers -------------------------------------------------
    @property
    def marker(self) -> dict:
        return json.loads(self.marker_path.read_text(encoding="utf-8"))

    def store_marker(self, mutate) -> dict:
        rec = self.marker
        mutate(rec)
        self.marker_path.write_text(json.dumps(rec, indent=1, sort_keys=True),
                                    encoding="utf-8")
        return rec

    def close_with(self, outcome: str, evidence: dict | None = None) -> dict:
        rec = self.store.unresolved(self.rig.rec["instance_id"])[0]
        return self.store.close(rec, outcome, closer="fixture", evidence=evidence or {})

    def replay(self, *, write_epoch: bool = False, owner: str = "owner", **spec_kw):
        return replay(self.root, self.rig, write_epoch=write_epoch, owner=owner, **spec_kw)

    def counts(self) -> dict:
        return counts(self.rig.transport, self.rig.adapter, self.rig.paths)


def unresolved_fixture(label: str, **spec_kw) -> Fixture:
    """Start one attempt, leave it UNRESOLVED with a durable marker + terminal history.

    Mirrors Codex's own reproduction: the prompt is still in `/queue` when the
    wait times out, so the attempt ends `unresolved` and keeps its marker; the
    server then finishes the prompt (history entry carrying node 9 `original.png`
    and node 10 `different.png`).
    """
    root = SCRATCH / label
    root.mkdir(parents=True, exist_ok=True)
    rig = make_rig(root, owner=spec_kw.get("owner", "owner"))
    rig.transport.queue_state["queue_running"] = [queue_item("pid-1", rig.adapter.client_id)]
    result = rig.adapter.run(base_spec(**spec_kw))
    assert result.status == "unresolved", f"fixture must end unresolved, got {result.status}"
    rig.gate.release()
    rig.lease.release()
    rig.transport.queue_state["queue_running"] = []
    entry = history_success("pid-1", "original.png")
    entry["outputs"]["10"] = {"images": [{"filename": "different.png", "subfolder": "",
                                         "type": "output"}]}
    rig.transport.history_map["pid-1"] = entry
    marker = next(rig.adapter.reservations.root.glob("*.reservation.json"))
    return Fixture(label, root, rig, marker)


def replay(root: Path, rig, *, write_epoch: bool = False, owner: str = "owner",
           requested=None, **spec_kw) -> dict:
    """Run one attempt over the SAME durable dirs with a FRESH process state.

    A fresh rig means a new lease + gate (i.e. an attempt by a process that
    starts after the previous one died), while `write_epoch=False` keeps the
    server boot identity, so the durable ledger is the only thing being tested.
    """
    same = make_rig(root, transport=rig.transport, write_epoch=write_epoch, owner=owner)
    spec_kw.setdefault("owner", owner)
    try:
        result = same.adapter.run(requested if requested is not None else base_spec(**spec_kw))
        verdict = _verdict(same, result=result)
    except BaseException as exc:  # noqa: BLE001 - a refusal is a recorded outcome
        verdict = _verdict(same, exc=exc)
    finally:
        if same.gate is not None and same.gate.held:
            same.gate.release()
        same.lease.release()
    return verdict


def counts(transport, adapter, paths) -> dict:
    store = adapter.reservations
    return {
        "post_calls": transport.submit_calls,
        "published_artifacts": None,          # filled by _verdict when a run returns
        "markers_on_disk": len(list(store.root.glob("*.reservation.json"))),
        "unresolved": len(store.unresolved()),
        "receipts": len(store.receipts()),
        "quarantined": len(store.quarantined()),
        "staged_files": sorted(p.name for p in Path(paths.root).rglob("*.png")),
    }


def _verdict(rig, *, result=None, exc=None) -> dict:
    d = counts(rig.transport, rig.adapter, rig.paths)
    d.update({
        "status": None, "error": None, "message": "", "adopted": None, "reused": None,
        "prompt_id": None, "published": [], "isolated_staging": [],
        "reservation_events": [e.get("action") for e in rig.adapter.reservation_events],
    })
    if result is not None:
        d.update(status=result.status, adopted=result.adopted, prompt_id=result.prompt_id,
                 published=[a.get("filename") for a in result.artifacts],
                 reused=any("reused durable validated evidence" in n for n in result.notes))
        d["published_artifacts"] = len(result.artifacts)
    if exc is not None:
        d["error"] = getattr(exc, "code", type(exc).__name__)
        d["message"] = str(exc)
        details = getattr(exc, "details", None) or {}
        if isinstance(details, dict):
            staging = details.get("staging")
            if isinstance(staging, dict):
                d["isolated_staging"] = [r.get("filename") for r in staging.get("records", [])]
    return d


def disposition(v: dict) -> str:
    """What the resolver did with the durable prior state (C02 row vocabulary)."""
    if v["error"]:
        return f"typed_refusal:{v['error']}"
    if v["reused"]:
        return "reused_validated_evidence"
    return f"ran_new_attempt:{v['status']}"


def chk(checks: list, name: str, expected, observed) -> None:
    checks.append({"check": name, "expected": expected, "observed": observed,
                   "ok": observed == expected})


def chk_in(checks: list, name: str, allowed, observed) -> None:
    checks.append({"check": name, "expected": f"one of {sorted(allowed)}",
                   "observed": observed, "ok": observed in allowed})


def marker_bytes(fx: Fixture) -> str:
    """sha256 of the marker file, or ABSENT when the resolver moved/deleted it."""
    import hashlib
    if not fx.marker_path.exists():
        return "ABSENT"
    return hashlib.sha256(fx.marker_path.read_bytes()).hexdigest()


# ------------------------------------------------------------------------- C01
def case_c01_unchanged_unresolved_replay() -> dict:
    """C01: an unchanged unresolved replay adopts its own prompt — total POST = 1."""
    fx = unresolved_fixture("c01")
    v = fx.replay()
    checks: list = []
    chk(checks, "status", "validated", v["status"])
    chk(checks, "adopted", True, v["adopted"])
    chk(checks, "published", ["original.png"], v["published"])
    chk(checks, "post_calls", 1, v["post_calls"])
    chk(checks, "markers_on_disk", 0, v["markers_on_disk"])
    chk(checks, "receipts", 1, v["receipts"])
    chk(checks, "staged_files", ["original.png"], v["staged_files"])
    return _row("C01", "c01_unchanged_unresolved_replay", checks, v)


# ------------------------------------------------------------------------- C02
def case_c02_receipt_replay() -> dict:
    """C02: a completed receipt for the SAME attempt ⇒ no implicit second attempt.

    Every variant (success / failure / cancel / unknown / provably-no-submit /
    previous boot) needs an explicit disposition and must never add a POST.
    """
    checks: list = []
    steps: dict = {}

    # -- success receipt, replayed by a fresh process on the same boot
    fx = unresolved_fixture("c02-success")
    first = fx.replay()                      # adopt + validate -> terminal_success
    steps["first_run"] = first
    chk(checks, "success.first_run.status", "validated", first["status"])
    second = fx.replay()
    steps["success_replay"] = second
    chk(checks, "success.no_new_post", 1, second["post_calls"])
    chk_in(checks, "success.disposition",
           {"reused_validated_evidence", f"typed_refusal:{AT_TERMINAL}"},
           disposition(second))
    chk(checks, "success.published_not_duplicated", [],
        [f for f in second["published"] if f != "original.png"])
    chk(checks, "success.dup_file_never_published", False, "duplicate.png" in second["staged_files"])
    chk(checks, "success.receipts_not_duplicated", 1, second["receipts"])

    # -- one receipt per non-success outcome, each replayed on the same boot
    for outcome, label in (("terminal_error", "failure"), ("cancelled", "cancel"),
                           ("rejected_no_submit", "provably_no_submit"),
                           ("mystery_outcome", "unknown")):
        fixture = unresolved_fixture(f"c02-{label}")
        closed = fixture.close_with(outcome, {"fixture": label})
        chk(checks, f"{label}.receipt_written", True, bool(closed.get("released")))
        v = fixture.replay()
        steps[label] = v
        chk(checks, f"{label}.no_new_post", 1, v["post_calls"])
        chk_in(checks, f"{label}.disposition", {f"typed_refusal:{AT_TERMINAL}"},
               disposition(v))
        chk(checks, f"{label}.no_artifact", [], v["published"])

    # -- receipt written by a PREVIOUS server boot (old epoch)
    old = unresolved_fixture("c02-old-epoch")
    old.replay()                              # success receipt for boot A
    old.rig.epoch.write("http://127.0.0.1:8199", "fake-0.0")   # server boots again
    v = old.replay()
    steps["old_epoch"] = v
    chk(checks, "old_epoch.no_new_post", 1, v["post_calls"])
    chk_in(checks, "old_epoch.disposition", {f"typed_refusal:{AT_TERMINAL}"}, disposition(v))
    return _row("C02", "c02_receipt_replay", checks, steps)


# ------------------------------------------------------------------------- C03
def case_c03_body_only_mutations() -> dict:
    """C03: body-only mutation with the digest left unchanged ⇒ typed refusal, 0 POST."""
    checks: list = []
    steps: dict = {}

    def mutate(mutator, label):
        fx = unresolved_fixture(f"c03-{label}")
        fx.store_marker(mutator)
        v = fx.replay()
        steps[label] = v
        chk(checks, f"{label}.no_new_post", 1, v["post_calls"])
        chk_in(checks, f"{label}.typed_refusal", {"MF_COMFY_CORRUPT_RESERVATION"},
               v["error"] or "")
        chk(checks, f"{label}.nothing_staged", [], v["staged_files"])
        chk(checks, f"{label}.nothing_published", [], v["published"])
        chk(checks, f"{label}.marker_kept", 1, v["markers_on_disk"])
        return fx

    def input_body_only(rec):
        rec["input_identity"] = {"source_sha256": "0" * 64}      # digest left unchanged

    def contract_node_only(rec):                                  # Codex repro #2
        node = rec["output_contract"]["nodes"].pop("9")
        rec["output_contract"]["nodes"]["10"] = node

    def pins_only(rec):                                           # Codex repro #3
        rec["output_contract"]["expected_artifact_pins"] = {"original.png": "0" * 64}

    def server_type_only(rec):
        rec["output_contract"]["nodes"]["9"]["server_types"] = ["input"]

    def media_type_only(rec):
        rec["output_contract"]["nodes"]["9"]["media_type"] = "video"

    def combined(rec):
        rec["input_identity"] = {"source_sha256": "1" * 64}
        rec["output_contract"]["nodes"]["9"]["kind"] = "videos"
        rec["output_contract"]["expected_artifact_pins"] = {"other.png": "2" * 64}

    mutate(input_body_only, "input_body_only")
    mutate(contract_node_only, "output_contract_node_only")
    mutate(pins_only, "pins_only")
    mutate(server_type_only, "server_type_only")
    mutate(media_type_only, "media_type_only")
    mutate(combined, "combined")

    # -- and the staging/publication distinction, on a CONSISTENT record whose
    #    pin is honestly wrong: the artifact may be isolated-staged, but it is
    #    never published and the failure must report it (Codex repro #3).
    fx = unresolved_fixture("c03-honest-pin")
    contract = fx.marker["output_contract"]
    contract.setdefault("expected_artifact_pins", {})["original.png"] = "0" * 64
    fx.store_marker(lambda rec: rec.update(output_contract=contract,
                                           output_contract_digest=ComfyStageAdapter
                                           .output_contract_digest(contract)))
    v = fx.replay(expected_artifact_hashes={"original.png": "0" * 64})
    steps["honest_pin_mismatch"] = v
    chk(checks, "honest_pin.no_new_post", 1, v["post_calls"])
    chk(checks, "honest_pin.error", "MF_COMFY_ARTIFACT_HASH_MISMATCH", v["error"] or "")
    chk(checks, "honest_pin.published", [], v["published"])
    chk(checks, "honest_pin.isolated_staging_reported", 1, len(v["isolated_staging"]))
    chk(checks, "honest_pin.staged_file_kept_as_evidence", ["original.png"], v["staged_files"])
    return _row("C03", "c03_body_only_mutations", checks, steps)


# ------------------------------------------------------------------------- C04
def case_c04_claimant_conflicts() -> dict:
    """C04: any wrong or multiple claimant ⇒ refuse; never pick the exact subset."""
    checks: list = []
    steps: dict = {}

    def add_second_claimant(fx: Fixture, name: str, mutator) -> None:
        rec = fx.marker
        mutator(rec)
        (fx.marker_path.parent / f"{name}.reservation.json").write_text(
            json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")

    # (a) one exact + one wrong-owner claimant on the same attempt (Codex repro #5)
    fx = unresolved_fixture("c04-one-exact-one-wrong")
    add_second_claimant(fx, "foreign-key", lambda r: r.update(owner="foreign", key="foreign-key"))
    v = fx.replay()
    steps["one_exact_one_wrong"] = v
    chk(checks, "one_exact_one_wrong.no_new_post", 1, v["post_calls"])
    chk_in(checks, "one_exact_one_wrong.typed_refusal", REFUSE_CODES, v["error"] or "")
    chk(checks, "one_exact_one_wrong.nothing_published", [], v["published"])
    chk(checks, "one_exact_one_wrong.no_receipt_written", 0, v["receipts"])
    chk(checks, "one_exact_one_wrong.both_markers_kept", 2, v["markers_on_disk"])

    # (b) two claimants for the same identity (a duplicate marker on disk)
    fx2 = unresolved_fixture("c04-two-exact")
    add_second_claimant(fx2, "zz-copy", lambda r: r.update(key="zz-copy"))
    v2 = fx2.replay()
    steps["two_exact"] = v2
    chk(checks, "two_exact.no_new_post", 1, v2["post_calls"])
    chk_in(checks, "two_exact.typed_refusal", REFUSE_CODES, v2["error"] or "")
    chk(checks, "two_exact.nothing_published", [], v2["published"])

    # (c) foreign owner/workspace only
    fx3 = unresolved_fixture("c04-foreign-owner")
    fx3.store_marker(lambda r: r.update(owner="foreign"))
    v3 = fx3.replay()
    steps["foreign_owner"] = v3
    chk(checks, "foreign_owner.no_new_post", 1, v3["post_calls"])
    chk(checks, "foreign_owner.error", "MF_COMFY_RESERVATION_CONFLICT", v3["error"] or "")

    # (d) alternate key/path: the file name encodes a different instance than the body
    fx4 = unresolved_fixture("c04-alternate-path")
    rec = fx4.marker
    (fx4.marker_path.parent / "zone__other-att.reservation.json").write_text(
        json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    fx4.marker_path.unlink()
    v4 = fx4.replay()
    steps["alternate_key_path"] = v4
    chk(checks, "alternate_key_path.no_new_post", 1, v4["post_calls"])
    chk_in(checks, "alternate_key_path.typed_refusal", REFUSE_CODES, v4["error"] or "")
    chk(checks, "alternate_key_path.nothing_published", [], v4["published"])

    # (e) cross-state: unresolved marker + quarantine record for the same work item
    fx5 = unresolved_fixture("c04-cross-state")
    rec = fx5.marker
    rec.update(state="quarantined", quarantine_reason="cross_state_fixture",
               quarantined_at=1.0, quarantine_evidence={}, closer="fixture")
    (fx5.marker_path.parent / f"{rec['key']}.quarantined.json").write_text(
        json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    v5 = fx5.replay()
    steps["cross_state"] = v5
    chk(checks, "cross_state.no_new_post", 1, v5["post_calls"])
    chk_in(checks, "cross_state.typed_refusal", REFUSE_CODES, v5["error"] or "")
    chk(checks, "cross_state.nothing_published", [], v5["published"])
    return _row("C04", "c04_claimant_conflicts", checks, steps)


# ------------------------------------------------------------------------- C05
def case_c05_missing_or_corrupt() -> dict:
    """C05: missing authority field / unreadable record ⇒ fail closed, evidence kept."""
    checks: list = []
    steps: dict = {}

    def strip(field, label):
        fx = unresolved_fixture(f"c05-{label}")
        fx.store_marker(lambda r: r.pop(field, None))
        before = marker_bytes(fx)
        v = fx.replay()
        steps[label] = v
        chk(checks, f"{label}.no_new_post", 1, v["post_calls"])
        chk_in(checks, f"{label}.fail_closed", {"MF_COMFY_CORRUPT_RESERVATION"}, v["error"] or "")
        chk(checks, f"{label}.nothing_published", [], v["published"])
        chk(checks, f"{label}.marker_kept_byte_identical", before, marker_bytes(fx))
        return fx

    strip("instance_id", "missing_instance_id")     # Codex repro #6 (lease.py authority)
    strip("attempt_id", "missing_attempt_id")
    strip("host", "missing_host")
    strip("schema", "missing_schema")

    # unreadable marker: never repaired, never rewritten
    fx = unresolved_fixture("c05-malformed")
    fx.marker_path.write_bytes(b'{"schema": "mf.comfy.prompt_reservation/1", "key": "trunc')
    before = marker_bytes(fx)
    v = fx.replay()
    steps["malformed_json"] = v
    chk(checks, "malformed_json.no_new_post", 1, v["post_calls"])
    chk(checks, "malformed_json.error", "MF_COMFY_CORRUPT_RESERVATION", v["error"] or "")
    chk(checks, "malformed_json.marker_kept_byte_identical", before, marker_bytes(fx))

    # a receipt that exists but carries no authority field (unreadable completion record)
    fx = unresolved_fixture("c05-receipt-authority")
    fx.store.close(fx.store.unresolved(fx.rig.rec["instance_id"])[0], "terminal_success",
                   closer="fixture")
    receipt = next(fx.store.closed_dir.glob("*.released.json"))
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload.pop("outcome", None)
    payload.pop("schema", None)
    receipt.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    v = fx.replay()
    steps["receipt_missing_authority"] = v
    chk(checks, "receipt_missing_authority.no_new_post", 1, v["post_calls"])
    chk_in(checks, "receipt_missing_authority.fail_closed",
           {"MF_COMFY_CORRUPT_RESERVATION"}, v["error"] or "")
    chk(checks, "receipt_missing_authority.nothing_published", [], v["published"])

    # unreadable receipt (truncated JSON) is unknown state, not "no receipt"
    fx = unresolved_fixture("c05-receipt-truncated")
    fx.store.close(fx.store.unresolved(fx.rig.rec["instance_id"])[0], "terminal_success",
                   closer="fixture")
    receipt = next(fx.store.closed_dir.glob("*.released.json"))
    receipt.write_bytes(b'{"schema": "mf.comfy.prompt_release/1", "key": "trunc')
    v = fx.replay()
    steps["receipt_truncated"] = v
    chk(checks, "receipt_truncated.no_new_post", 1, v["post_calls"])
    chk_in(checks, "receipt_truncated.fail_closed",
           {"MF_COMFY_CORRUPT_RESERVATION"}, v["error"] or "")
    return _row("C05", "c05_missing_or_corrupt", checks, steps)


# ------------------------------------------------------------------------- C06
def case_c06_legacy_rows_retained() -> dict:
    """C06: the two already-correct refusals must not regress."""
    checks: list = []
    steps: dict = {}

    fx = unresolved_fixture("c06-old-pin")
    spec = base_spec()
    from mf_comfy.pinning import hash_workflow
    spec.workflow_sha256 = hash_workflow(spec.graph)
    spec.graph["3"]["inputs"]["seed"] = 77              # graph changed, pin kept
    v = fx.replay(requested=spec)
    steps["changed_graph_valid_old_pin"] = v
    chk(checks, "changed_graph_valid_old_pin.error", "MF_COMFY_WORKFLOW_HASH_MISMATCH",
        v["error"] or "")
    chk(checks, "changed_graph_valid_old_pin.no_new_post", 1, v["post_calls"])
    chk(checks, "changed_graph_valid_old_pin.nothing_published", [], v["published"])
    chk(checks, "changed_graph_valid_old_pin.marker_kept", 1, v["markers_on_disk"])

    fx2 = unresolved_fixture("c06-foreign-owner")
    v2 = fx2.replay(owner="foreign")
    steps["foreign_owner_completed"] = v2
    chk(checks, "foreign_owner_completed.error", "MF_COMFY_RESERVATION_CONFLICT",
        v2["error"] or "")
    chk(checks, "foreign_owner_completed.no_new_post", 1, v2["post_calls"])
    chk(checks, "foreign_owner_completed.nothing_published", [], v2["published"])
    return _row("C06", "c06_legacy_rows_retained", checks, steps)


# ------------------------------------------------------------------------- C07
def case_c07_independent_new_work() -> dict:
    """C07: a genuinely NEW work item after a terminal one must still run."""
    checks: list = []
    steps: dict = {}

    fx = unresolved_fixture("c07-new-attempt")
    first = fx.replay()                                  # attempt 'att' -> terminal_success
    steps["terminal_attempt"] = first
    chk(checks, "terminal_attempt.status", "validated", first["status"])
    chk(checks, "terminal_attempt.receipts", 1, first["receipts"])

    fx.rig.transport.history_map["pid-2"] = history_success("pid-2", "second_attempt.png")
    second = fx.replay(attempt_id="att-2")
    steps["independent_new_attempt"] = second
    chk(checks, "independent_new_attempt.status", "validated", second["status"])
    chk(checks, "independent_new_attempt.post_calls", 2, second["post_calls"])
    chk(checks, "independent_new_attempt.published", ["second_attempt.png"], second["published"])
    chk(checks, "independent_new_attempt.receipts", 2, second["receipts"])

    # ACK absence is not proof: only a durable submit_state=opening with a
    # provably gone opener unlocks a release.
    dead = {"submit_state": "opening", "submit_owner_host": __import__("socket").gethostname(),
            "submit_owner_pid": 999999}
    checks.append({"check": "ack_absence.opening_with_dead_opener_is_proof", "expected": True,
                   "observed": submit_provably_never_started(dead),
                   "ok": submit_provably_never_started(dead) is True})
    for state in ("inflight", "acked", "ambiguous", None):
        rec = dict(dead, submit_state=state)
        got = submit_provably_never_started(rec)
        checks.append({"check": f"ack_absence.{state or 'legacy'}_is_not_proof", "expected": False,
                       "observed": got, "ok": got is False})
    return _row("C07", "c07_independent_new_work", checks, steps)


def _row(row_id: str, case: str, checks: list, steps) -> dict:
    return {"row": row_id, "case": case, "checks": checks,
            "passed": sum(1 for c in checks if c["ok"]), "total": len(checks),
            "ok": all(c["ok"] for c in checks), "steps": steps}


CASES = {
    "c01_unchanged_unresolved_replay": case_c01_unchanged_unresolved_replay,
    "c02_receipt_replay": case_c02_receipt_replay,
    "c03_body_only_mutations": case_c03_body_only_mutations,
    "c04_claimant_conflicts": case_c04_claimant_conflicts,
    "c05_missing_or_corrupt": case_c05_missing_or_corrupt,
    "c06_legacy_rows_retained": case_c06_legacy_rows_retained,
    "c07_independent_new_work": case_c07_independent_new_work,
}


def run_case(name: str) -> dict:
    return CASES[name]()


def accounting() -> dict:
    """Full-ledger accounting across every case tree of this run.

    Counts ALL ledger files ON DISK (not a trusted per-case prefix), so the
    runner can prove the per-case counters are not a truncated subset.
    """
    on_disk = {"markers": 0, "receipts": 0, "quarantined": 0, "staged_png": 0}
    if not SCRATCH.exists():
        return on_disk
    for p in SCRATCH.rglob("*"):
        if not p.is_file():
            continue
        if p.name.endswith(".reservation.json"):
            on_disk["markers"] += 1
        elif p.name.endswith(".released.json"):
            on_disk["receipts"] += 1
        elif p.name.endswith(".quarantined.json"):
            on_disk["quarantined"] += 1
        elif p.suffix.lower() == ".png":
            on_disk["staged_png"] += 1
    return on_disk
