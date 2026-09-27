"""R27-03 frozen rows: a same-attempt gate race must yield exactly ONE POST.

Frozen row names — the Manager MATRIX gates on these exact 8 tests:

    test_r27_same_attempt_race_a_success_b_waits_single_post
    test_r27_same_attempt_race_a_failure_b_refuses
    test_r27_unresolved_inflight_second_caller_refused
    test_r27_valid_exact_replay_reuses_receipt
    test_r27_different_workflow_input_owner_fail_closed
    test_r27_true_orphan_requeues_once
    test_r27_read_error_is_not_absence
    test_r27_independent_attempt_control_two_posts

"Two live participants" means REAL concurrent callers (threads) with a bounded
rendezvous at the real gate (`GpuStageGate.acquire`) or at the real POST
(`FakeTransport.submit`), never a sequential simulation of one caller. Every row
records the rendezvous point used, the winner/submit count and the whole durable
state on disk (markers / receipts / quarantined / staged artifacts).

`_row_*` builders return the RAW record plus its checks, so this module is the
single source of truth for both the pytest rows and the raw evidence runner
(`COMFY/raw/run_matrix_r27.py`).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

from fake_transport import history_error, history_success, make_rig, make_spec
from mf_comfy.contract import StageInput

SAME_ATTEMPT = "same-attempt"
SAME_OWNER = "same-owner"
TERMINAL_OUTPUTS = {"9": {"kind": "images", "media_type": "image"}}
REFUSAL_CODES = ("MF_COMFY_ATTEMPT_ALREADY_TERMINAL", "MF_COMFY_RESERVATION_CONFLICT",
                 "MF_COMFY_CORRUPT_RESERVATION", "MF_COMFY_UNRESOLVED_RESERVATION")
# A pid that is provably not alive on this host: the crash-window shape.
DEAD_PID = 999999

SCRATCH = Path(os.environ.get("MF_R27_TEST_SCRATCH")
               or (Path(os.environ.get("TEMP") or r"C:/Users/Admin/AppData/Local/Temp"))
               ) / f"r27t_{os.getpid()}"


# ----------------------------------------------------------------- small tools
def _sha(path) -> str:
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "ABSENT"


def _load(path) -> dict:
    """Read one durable record; an UNREADABLE record is DATA, never an exception.

    R27-6/R27-7 must both MEASURE a marker that is deliberately not decodable
    (a truncated body; here, an identity-incomplete body). Raising made the
    MEASURING HELPER the thing that failed, so the row reported a crash instead
    of what the ledger actually did. The read error is recorded as a field
    rather than swallowed: returning `{}` would make an unreadable record
    indistinguishable from an empty one, the exact confusion the adapter's own
    fail-closed rules exist to prevent.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"read_error": f"{type(exc).__name__}: {exc}", "raw": None}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        return {"read_error": f"json.JSONDecodeError: {exc}", "raw": text}


def _fresh(label: str) -> Path:
    root = SCRATCH / label
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _spec(attempt_id: str, *, stage_id: str = "t", workflow_id: str = "wf_fake",
          owner: str = SAME_OWNER):
    return make_spec(attempt_id=attempt_id, stage_id=stage_id, workflow_id=workflow_id,
                     owner=owner, terminal_outputs=TERMINAL_OUTPUTS,
                     stage_timeout_s=5.0, poll_s=1.0)


def _stage_input(*, source_sha256: str = "b" * 64):
    """The REAL `StageInput` a caller declares -- the shape `run()` builds itself.

    `run()` never calls `_claim` with `None`: it substitutes
    `StageInput(stage_id=spec.stage_id, staging_root=...)` before anything else,
    so the production path can only ever record a SIX-KEY `input_identity` body.
    A fixture that passes `None` to `_claim` writes `input_identity: {}` next to a
    recorded `input_digest`; `lease.body_digest_problems()` then correctly reads
    that as a digest recorded WITHOUT its body (identity-incomplete) and the
    ledger fails the attempt closed as CORRUPT long before the requeue path this
    row is about. Any row authoring a durable record goes through this helper.
    """
    return StageInput(stage_id="t", project_id="proj-r27", job_id="job-r27",
                      shot_id="shot-r27", source_sha256=source_sha256,
                      source_frame_range=[0, 24],
                      reference_assets={"ref_plate": "c" * 64})


def _disk_state(root: Path) -> dict:
    """Every durable byte this row left behind, measured on disk (not a counter)."""
    store_root = Path(root) / "reservations"
    stage_root = Path(root) / "stage"

    def bucket(pattern: str) -> list:
        return [{"path": str(p), "sha256": _sha(p), "record": _load(p)}
                for p in sorted(store_root.rglob(pattern)) if p.is_file()]

    return {
        "markers": bucket("*.reservation.json"),
        "receipts": bucket("*.released.json"),
        "quarantined": bucket("*.quarantined.json"),
        "staged": [{"name": p.name, "sha256": _sha(p), "size_bytes": p.stat().st_size}
                   for p in sorted(stage_root.rglob("*")) if p.is_file()],
    }


def _outcome(rig, spec, stage_input=None) -> dict:
    """Run one caller; a refusal is a recorded outcome, never swallowed."""
    try:
        out = rig.adapter.run(spec, stage_input)
        return {"status": out.status, "adopted": out.adopted, "prompt_id": out.prompt_id,
                "artifacts": [dict(a) for a in out.artifacts],
                "published": [a.get("filename") for a in out.artifacts],
                "notes": list(out.notes), "reservation": out.reservation,
                "events": [e.get("action") for e in rig.adapter.reservation_events],
                "submit_count": rig.adapter.submit_count}
    except BaseException as exc:  # noqa: BLE001 - a refusal is a recorded outcome
        return {"status": None, "error": getattr(exc, "code", type(exc).__name__),
                "exception": type(exc).__name__, "message": str(exc),
                "details": getattr(exc, "details", None), "published": [], "artifacts": [],
                "events": [e.get("action") for e in rig.adapter.reservation_events],
                "submit_count": rig.adapter.submit_count}


def _race_gate(root: Path, *, spec_a, spec_b, history: dict, owner_a: str = SAME_OWNER,
               owner_b: str | None = None, input_a=None, input_b=None) -> dict:
    """Two LIVE callers, caller B rendezvousing at the REAL gate.

    B is parked at `GpuStageGate.acquire` before the real critical section is
    entered; A then runs to completion; B is permitted to enter the real gate.
    That is the reviewer's window: B inspected the durable state while it was
    still empty.
    """
    a = make_rig(root, owner=owner_a)
    b = make_rig(root, owner=owner_b or owner_a, transport=a.transport, write_epoch=False)
    a.transport.history_map.update(history)
    reached, permit, a_done = threading.Event(), threading.Event(), threading.Event()
    trace: list = []
    real_acquire = b.gate.acquire

    def gated_acquire(*args, **kwargs):
        trace.append({"event": "B_at_real_gate_acquire", "t": time.monotonic(),
                      "union_checks": [e.get("action") for e in b.adapter.reservation_events]})
        reached.set()
        if not permit.wait(30):
            raise RuntimeError("bounded B rendezvous timeout")
        trace.append({"event": "B_enter_real_gate_acquire", "t": time.monotonic()})
        return real_acquire(*args, **kwargs)

    b.gate.acquire = gated_acquire
    results: dict = {}

    def call(label, rig, spec, stage_input, done):
        try:
            results[label] = _outcome(rig, spec, stage_input)
        finally:
            trace.append({"event": label + "_finished", "t": time.monotonic()})
            if done is not None:
                done.set()

    t_a = threading.Thread(target=call, args=("A", a, spec_a, input_a, a_done), name="r27-A")
    t_b = threading.Thread(target=call, args=("B", b, spec_b, input_b, None), name="r27-B")
    t_b.start()
    rendezvous = reached.wait(30)
    a_completed = False
    if rendezvous:
        t_a.start()
        a_completed = a_done.wait(30)
    permit.set()
    if t_a.ident is not None:
        t_a.join(30)
    t_b.join(30)
    if b.gate.held:
        b.gate.release()
    return {
        "rendezvous_point": "thread B parked at the real GpuStageGate.acquire "
                            "(before the real critical section is entered)",
        "rendezvous_reached": rendezvous,
        "a_completed_before_b_gate": a_completed,
        "threads_joined": not t_a.is_alive() and not t_b.is_alive(),
        "submit_calls": a.transport.submit_calls,
        "A": results.get("A", {}), "B": results.get("B", {}),
        "trace": trace,
        "disk": _disk_state(root),
    }


# ------------------------------------------------------------------ row checks
def _chk(checks: list, name: str, expected, observed) -> None:
    checks.append({"check": name, "expected": expected, "observed": observed,
                   "ok": observed == expected})


def _chk_in(checks: list, name: str, allowed, observed) -> None:
    checks.append({"check": name, "expected": f"one of {sorted(allowed)}",
                   "observed": observed, "ok": observed in allowed})


def _row(row_id: str, case: str, record: dict, checks: list) -> dict:
    return {"row": row_id, "case": case, "record": record, "checks": checks,
            "passed": sum(1 for c in checks if c["ok"]), "total": len(checks),
            "ok": all(c["ok"] for c in checks)}


def _explain(row: dict) -> str:
    bad = [c for c in row["checks"] if not c["ok"]]
    return (f"{row['row']}: {len(bad)}/{len(row['checks'])} check(s) failed: "
            + "; ".join(f"{c['check']} expected={c['expected']!r} observed={c['observed']!r}"
                        for c in bad[:8]))


def _receipt_for(disk: dict, attempt_id: str) -> dict:
    for item in disk["receipts"]:
        if item["record"].get("attempt_id") == attempt_id:
            return item
    return {}


# ------------------------------------------------------------------- ROWS 1-2
def _row_a_success_b_waits() -> dict:
    """A commits terminal_success while B waits at the gate: ONE POST in total."""
    root = _fresh("r1")
    race = _race_gate(root, spec_a=_spec(SAME_ATTEMPT), spec_b=_spec(SAME_ATTEMPT),
                      history={"pid-1": history_success("pid-1", "first.png"),
                               "pid-2": history_success("pid-2", "duplicate.png")})
    disk, a_side, b_side = race["disk"], race["A"], race["B"]
    a_art = (a_side.get("artifacts") or [{}])[0]
    b_art = (b_side.get("artifacts") or [{}])[0]
    receipt = _receipt_for(disk, SAME_ATTEMPT)
    close_ev = ((receipt.get("record") or {}).get("close_evidence") or {})
    checks: list = []
    _chk(checks, "rendezvous_reached", True, race["rendezvous_reached"])
    _chk(checks, "threads_joined", True, race["threads_joined"])
    _chk(checks, "A_completed_before_B_entered_gate", True, race["a_completed_before_b_gate"])
    _chk(checks, "A_status_validated", "validated", a_side.get("status"))
    _chk(checks, "ONE_post_total", 1, race["submit_calls"])
    _chk(checks, "B_status_validated", "validated", b_side.get("status"))
    _chk(checks, "B_adopted_committed_evidence", True, bool(b_side.get("adopted")))
    _chk(checks, "B_returned_no_error", None, b_side.get("error"))
    _chk(checks, "B_published_first_png", ["first.png"], b_side.get("published"))
    _chk(checks, "B_artifact_sha_equals_A_artifact_sha", a_art.get("sha256"), b_art.get("sha256"))
    _chk(checks, "B_artifact_bytes_match_disk", _sha(b_art.get("staged_path")), b_art.get("sha256"))
    _chk(checks, "B_reused_from_a_receipt", True, bool(b_art.get("reused_from")))
    _chk(checks, "B_prompt_id_is_A_prompt", a_side.get("prompt_id"), b_side.get("prompt_id"))
    _chk(checks, "receipt_prompt_id_is_A_prompt", a_side.get("prompt_id"),
         receipt.get("record", {}).get("prompt_id"))
    _chk(checks, "receipt_submit_count", 1, receipt.get("record", {}).get("submit_count"))
    _chk(checks, "receipt_outcome", "terminal_success", receipt.get("record", {}).get("outcome"))
    # receipt <-> returned artifact must not contradict each other
    _chk(checks, "receipt_artifact_filename", [b_art.get("filename")],
         [a_.get("filename") for a_ in (close_ev.get("artifacts") or [])])
    _chk(checks, "receipt_artifact_sha", b_art.get("sha256"),
         (close_ev.get("artifacts") or [{}])[0].get("sha256"))
    _chk(checks, "staged_has_only_first_png", ["first.png"],
         [s["name"] for s in disk["staged"]])
    _chk(checks, "no_duplicate_artifact_published", False,
         "duplicate.png" in [s["name"] for s in disk["staged"]])
    _chk(checks, "no_marker_left_on_disk", 0, len(disk["markers"]))
    _chk(checks, "exactly_one_receipt", 1, len(disk["receipts"]))
    _chk(checks, "B_reenumerated_union_inside_gate", 2,
         b_side.get("events", []).count("durable_union_enumerated"))
    _chk(checks, "B_decision_replayed_terminal_receipt", True,
         "replayed_terminal_receipt" in b_side.get("events", []))
    _chk(checks, "B_never_submitted", 0, b_side.get("submit_count"))
    return _row("R27-1", "same_attempt_race_a_success_b_waits_single_post", race, checks)


def _row_a_failure_b_refuses() -> dict:
    """A commits a FAILED terminal outcome while B waits: B refuses, no 2nd POST."""
    root = _fresh("r2")
    race = _race_gate(root, spec_a=_spec(SAME_ATTEMPT), spec_b=_spec(SAME_ATTEMPT),
                      history={"pid-1": history_error("pid-1", "synthetic node explosion"),
                               "pid-2": history_success("pid-2", "duplicate.png")})
    disk, a_side, b_side = race["disk"], race["A"], race["B"]
    receipt = _receipt_for(disk, SAME_ATTEMPT)
    checks: list = []
    _chk(checks, "rendezvous_reached", True, race["rendezvous_reached"])
    _chk(checks, "threads_joined", True, race["threads_joined"])
    _chk(checks, "A_completed_before_B_entered_gate", True, race["a_completed_before_b_gate"])
    _chk(checks, "A_failed_typed", True, bool(a_side.get("error")))
    _chk(checks, "A_committed_terminal_error_receipt", "terminal_error",
         receipt.get("record", {}).get("outcome"))
    _chk(checks, "ONE_post_total", 1, race["submit_calls"])
    _chk_in(checks, "B_typed_refusal", REFUSAL_CODES, b_side.get("error") or "")
    _chk(checks, "B_refused_as_attempt_already_terminal", "MF_COMFY_ATTEMPT_ALREADY_TERMINAL",
         b_side.get("error") or "")
    _chk(checks, "B_no_phantom_success", None, b_side.get("status"))
    _chk(checks, "B_published_nothing", [], b_side.get("published"))
    _chk(checks, "B_receipt_id_points_at_A_receipt", True,
         str((b_side.get("details") or {}).get("receipt") or "").endswith(".released.json"))
    _chk(checks, "staged_has_no_duplicate_png", False,
         "duplicate.png" in [s["name"] for s in disk["staged"]])
    _chk(checks, "no_marker_left_on_disk", 0, len(disk["markers"]))
    _chk(checks, "exactly_one_receipt", 1, len(disk["receipts"]))
    _chk(checks, "B_reenumerated_union_inside_gate", 2,
         b_side.get("events", []).count("durable_union_enumerated"))
    _chk(checks, "B_never_submitted", 0, b_side.get("submit_count"))
    return _row("R27-2", "same_attempt_race_a_failure_b_refuses", race, checks)


# ---------------------------------------------------------------------- ROW 3
def _row_unresolved_inflight_second_caller() -> dict:
    """A's POST is live and A's reservation is unresolved: B is refused, 0 extra POSTs."""
    root = _fresh("r3")
    a = make_rig(root, owner=SAME_OWNER)
    b = make_rig(root, owner=SAME_OWNER, transport=a.transport, write_epoch=False)
    a.transport.history_map.update({"pid-1": history_success("pid-1", "first.png")})
    inside_post, allow_post = threading.Event(), threading.Event()
    a_done: dict = {}

    def submit_hook(client_id):
        inside_post.set()
        if not allow_post.wait(30):
            raise RuntimeError("bounded POST rendezvous timeout")

    a.transport.submit_hook = submit_hook

    def caller_a():
        a_done.update(_outcome(a, _spec(SAME_ATTEMPT)))

    t_a = threading.Thread(target=caller_a, name="r27-A-in-post")
    t_a.start()
    entered = inside_post.wait(30)
    marker = (Path(root) / "reservations").rglob("*.reservation.json")
    markers = [p for p in marker if p.is_file()]
    marker_before = {str(p): _sha(p) for p in markers}
    inflight = _load(markers[0]).get("submit_state") if markers else None
    b_side = _outcome(b, _spec(SAME_ATTEMPT))
    during = {str(p): _sha(p) for p in (Path(root) / "reservations").rglob("*.reservation.json")
              if p.is_file()}
    submit_during = a.transport.submit_calls
    allow_post.set()
    t_a.join(30)
    disk = _disk_state(root)
    checks: list = []
    _chk(checks, "rendezvous_reached_at_real_post", True, entered)
    _chk(checks, "A_marker_durable_before_B_runs", 1, len(markers))
    _chk(checks, "A_submit_state_inflight", "inflight", inflight)
    _chk(checks, "A_post_in_flight_during_B", 1, submit_during)
    _chk(checks, "B_refused_unresolved_reservation", "MF_COMFY_UNRESOLVED_RESERVATION",
         b_side.get("error") or "")
    _chk(checks, "ZERO_extra_post_by_B", 1, submit_during)
    _chk(checks, "B_never_submitted", 0, b_side.get("submit_count"))
    _chk(checks, "A_marker_preserved_through_B", marker_before, during)
    _chk(checks, "B_published_nothing", [], b_side.get("published"))
    _chk(checks, "A_still_validated_after_release", "validated", a_done.get("status"))
    _chk(checks, "A_single_post_total", 1, a.transport.submit_calls)
    _chk(checks, "no_marker_left_on_disk", 0, len(disk["markers"]))
    _chk(checks, "A_receipt_terminal_success", "terminal_success",
         _receipt_for(disk, SAME_ATTEMPT).get("record", {}).get("outcome"))
    return _row("R27-3", "unresolved_inflight_second_caller_refused",
                {"rendezvous_point": "thread A parked inside the real POST "
                                     "(FakeTransport.submit via submit_hook); B runs while A is "
                                     "in flight and must be refused by the real gate",
                 "rendezvous_reached": entered, "submit_calls_while_B_refused": submit_during,
                 "A": a_done, "B": b_side,
                 "marker_sha_before": marker_before, "marker_sha_during_B": during,
                 "marker_submit_state": inflight, "disk": disk}, checks)


# ---------------------------------------------------------------------- ROW 4
def _row_valid_exact_replay() -> dict:
    """The receipt is already committed: an exact replay adopts it, no gate/POST."""
    root = _fresh("r4")
    a = make_rig(root, owner=SAME_OWNER)
    a.transport.history_map.update({"pid-1": history_success("pid-1", "first.png"),
                                    "pid-2": history_success("pid-2", "duplicate.png")})
    first = _outcome(a, _spec(SAME_ATTEMPT))
    receipt_path = _receipt_for(_disk_state(root), SAME_ATTEMPT)["path"]
    receipt_sha_before = _sha(receipt_path)
    b = make_rig(root, owner=SAME_OWNER, transport=a.transport, write_epoch=False)
    second = _outcome(b, _spec(SAME_ATTEMPT))
    disk = _disk_state(root)
    art = (second.get("artifacts") or [{}])[0]
    checks: list = []
    _chk(checks, "first_caller_validated", "validated", first.get("status"))
    _chk(checks, "first_caller_posted_once", 1, a.transport.submit_calls)
    _chk(checks, "replay_status_validated", "validated", second.get("status"))
    _chk(checks, "replay_adopted", True, bool(second.get("adopted")))
    _chk(checks, "replay_never_submitted", 0, second.get("submit_count"))
    _chk(checks, "replay_published_first_png", ["first.png"], second.get("published"))
    _chk(checks, "replay_reuses_receipt_path", receipt_path, art.get("reused_from"))
    _chk(checks, "replay_artifact_matches_disk", _sha(art.get("staged_path")), art.get("sha256"))
    _chk(checks, "replay_took_no_gate", False, b.gate.held)
    _chk(checks, "TOTAL_one_post", 1, a.transport.submit_calls)
    _chk(checks, "receipt_unchanged_by_replay", receipt_sha_before, _sha(receipt_path))
    _chk(checks, "exactly_one_receipt", 1, len(disk["receipts"]))
    _chk(checks, "no_duplicate_artifact", False,
         "duplicate.png" in [s["name"] for s in disk["staged"]])
    return _row("R27-4", "valid_exact_replay_reuses_receipt",
                {"rendezvous_point": "none: the durable receipt is committed BEFORE the replay "
                                     "caller starts (exact-replay path, no gate race)",
                 "submit_calls": a.transport.submit_calls, "first": first, "replay": second,
                 "disk": disk}, checks)


# ---------------------------------------------------------------------- ROW 5
def _row_identity_variants_fail_closed() -> dict:
    """One field changed (workflow / input digest / owner): V is refused, 0 foreign artifacts.

    Each variant runs with TWO live participants: V parked at the real gate, the
    owner A allowed to commit first. Without the in-gate re-resolution V would
    take the gate on a stale decision and publish its own artifact.
    """
    variants = {
        "workflow": {"spec_b": _spec(SAME_ATTEMPT, workflow_id="wf-other")},
        "input_digest": {"spec_b": _spec(SAME_ATTEMPT),
                         "input_b": StageInput(stage_id="t", source_sha256="d" * 64)},
        "owner": {"spec_b": _spec(SAME_ATTEMPT, owner="other-owner")},
    }
    record: dict = {"rendezvous_point": "variant caller V parked at the real "
                                        "GpuStageGate.acquire; owner A commits first",
                    "variants": {}}
    checks: list = []
    for name, override in variants.items():
        root = _fresh(f"r5_{name}")
        race = _race_gate(root, spec_a=_spec(SAME_ATTEMPT), history={
            "pid-1": history_success("pid-1", "first.png"),
            "pid-2": history_success("pid-2", "duplicate.png")}, **override)
        disk, v_side = race["disk"], race["B"]
        staged = [s["name"] for s in disk["staged"]]
        record["variants"][name] = {
            "changed_field": name, "A": race["A"], "V": v_side,
            "submit_calls": race["submit_calls"], "disk": disk,
            "rendezvous_reached": race["rendezvous_reached"],
            "threads_joined": race["threads_joined"]}
        _chk(checks, f"{name}.A_committed", "validated", race["A"].get("status"))
        _chk(checks, f"{name}.ONE_post_total", 1, race["submit_calls"])
        _chk_in(checks, f"{name}.V_typed_refusal", REFUSAL_CODES, v_side.get("error") or "")
        _chk(checks, f"{name}.V_published_nothing", [], v_side.get("published"))
        _chk(checks, f"{name}.V_no_phantom_success", None, v_side.get("status"))
        _chk(checks, f"{name}.V_never_submitted", 0, v_side.get("submit_count"))
        _chk(checks, f"{name}.no_foreign_artifact_staged", ["first.png"], staged)
        _chk(checks, f"{name}.V_reenumerated_union_inside_gate", 2,
             v_side.get("events", []).count("durable_union_enumerated"))
        _chk(checks, f"{name}.no_marker_left", 0, len(disk["markers"]))
        _chk(checks, f"{name}.one_receipt", 1, len(disk["receipts"]))
    return _row("R27-5", "different_workflow_input_owner_fail_closed", record, checks)


# ---------------------------------------------------------------------- ROW 6
def _row_true_orphan_requeues_once() -> dict:
    """A provably-never-POSTed orphan is released and the re-attempt POSTs exactly once."""
    root = _fresh("r6")
    rig = make_rig(root, owner=SAME_OWNER)
    spec = _spec(SAME_ATTEMPT)
    # The orphan is opened by the REAL claim of a REAL declared stage input, the
    # same identity the re-attempt below presents. `_claim(spec, None, ...)` is
    # NOT a production shape (run() substitutes a StageInput first): it produced an
    # identity-incomplete marker that the ledger refused as CORRUPT.
    stage_input = _stage_input()
    claim = rig.adapter._claim(spec, stage_input, SAME_ATTEMPT)
    contract = rig.adapter._normalized_output_contract(spec)
    orphan = rig.adapter.reservations.open(
        rig.rec, SAME_ATTEMPT, stage_id=spec.stage_id, owner=claim["owner"],
        client_id="orphan-client-never-posted", workflow_id=claim["workflow_id"],
        workflow_sha256=claim["workflow_sha256"], input_digest=claim["input_digest"],
        input_identity=claim["input_identity"], output_contract=contract,
        output_contract_digest=rig.adapter.output_contract_digest(contract),
        note="orphan fixture: opened, POST never attempted")
    orphan_path = Path(orphan["path"])
    # The crash-window shape a real process leaves when it dies between open() and
    # submit(): still `opening`, opener pid provably not alive on this host.
    body = _load(orphan_path)
    body["submit_state"] = "opening"
    body["submit_owner_pid"] = DEAD_PID
    orphan_path.write_text(json.dumps(body, indent=1, sort_keys=True), encoding="utf-8")
    orphan_sha = _sha(orphan_path)
    rig.transport.history_map.update({"pid-1": history_success("pid-1", "requeued.png")})
    caller = make_rig(root, owner=SAME_OWNER, transport=rig.transport, write_epoch=False)
    outcome = _outcome(caller, _spec(SAME_ATTEMPT), stage_input)
    # The requeued run's OWN close attempt, verbatim: this is the second write for
    # one attempt slot, i.e. where the store's one-receipt-per-attempt invariant
    # refuses to record the terminal outcome of a requeued attempt.
    close_attempt = next((e for e in caller.adapter.reservation_events
                          if e.get("action") == "close"), {})
    disk = _disk_state(root)
    outcomes = {r["record"].get("outcome"): r for r in disk["receipts"]}
    checks: list = []
    # The raw CAUSE this row was repaired for, measured on the fixture body: the
    # orphan must be a legal durable record, not identity-incomplete. Identity
    # problems (`input_identity`/`input_digest` pairing) carry no `class` key.
    _chk(checks, "orphan_fixture_identity_complete", 0,
         len([p for p in rig.adapter._record_integrity(
             body, what="unresolved reservation", path=orphan_path,
             suffix=rig.adapter.reservations.SUFFIX) if not p.get("class")]))
    _chk(checks, "orphan_fixture_identity_body_non_empty", True,
         bool(body.get("input_identity")))
    _chk(checks, "orphan_released_and_gone", False, orphan_path.exists())
    _chk(checks, "requeue_validated", "validated", outcome.get("status"))
    _chk(checks, "exactly_ONE_post", 1, rig.transport.submit_calls)
    _chk(checks, "requeue_published_new_artifact", ["requeued.png"], outcome.get("published"))
    _chk(checks, "orphan_released_once_as_not_accepted", True, "not_accepted" in outcomes)
    _chk(checks, "no_marker_left_on_disk", 0, len(disk["markers"]))
    # ONE receipt per (instance, attempt): the store refuses the second write for
    # the same slot (exclusive create, first write wins -- asserted green by
    # `test_reservation.py::test_reservation_release_is_exactly_once_even_when_racing`).
    # The release above consumed this attempt's slot, so the requeued run's terminal
    # outcome is dropped and the ledger keeps the release. That is an OPEN FINDING
    # (the slot belongs to lease.py, outside this task's write-set), so it is pinned
    # here rather than blessed, and the adapter is required to surface it:
    # silence would hide a completed run whose validated evidence is unreusable.
    _chk(checks, "exactly_ONE_receipt_for_the_attempt", 1, len(disk["receipts"]))
    _chk(checks, "the_receipt_outcome_is_the_release", "not_accepted",
         outcomes.get("not_accepted", {}).get("record", {}).get("outcome"))
    _chk(checks, "not_accepted_release_count", 1,
         outcomes.get("not_accepted", {}).get("record", {}).get("release_count"))
    _chk(checks, "OPEN_FINDING_terminal_close_refused_by_the_store", True,
         bool((close_attempt.get("result") or {}).get("already_released")))
    _chk(checks, "OPEN_FINDING_recorded_outcome_is_not_the_terminal_one",
         "not_accepted", (close_attempt.get("result") or {}).get("outcome"))
    _chk(checks, "OPEN_FINDING_surfaced_as_a_typed_event", True,
         "terminal_outcome_not_durably_recorded" in outcome.get("events", []))
    _chk(checks, "OPEN_FINDING_the_receipt_keeps_no_terminal_evidence", None,
         outcomes.get("not_accepted", {}).get("record", {}).get("prompt_id"))
    _chk(checks, "release_preceded_the_single_post", True,
         "released_not_accepted" in outcome.get("events", []))
    _chk(checks, "requeue_did_not_resubmit_twice", 1, outcome.get("submit_count"))
    return _row("R27-6", "true_orphan_requeues_once",
                {"rendezvous_point": "none needed: the orphan is committed before the attempt "
                                     "starts; the row proves the fix does not over-lock the "
                                     "legitimate single requeue",
                 "orphan_sha256": orphan_sha, "orphan_record": body,
                 "outcome": outcome, "terminal_close_attempt": close_attempt,
                 "open_finding": {
                     "id": "R27-6-F1",
                     "severity": "P1",
                     "owner_file_outside_write_set": "mf_comfy/lease.py",
                     "what": "the single receipt of an attempt is consumed by the "
                             "orphan release, so a same-attempt requeue that "
                             "completes cannot durably record its terminal outcome",
                     "measured": {"close_result": close_attempt.get("result"),
                                  "run_status": outcome.get("status"),
                                  "submit_count": outcome.get("submit_count"),
                                  "receipts_on_disk": len(disk["receipts"])}},
                 "disk": disk}, checks)


# ---------------------------------------------------------------------- ROW 7
def _row_read_error_is_not_absence() -> dict:
    """An unreadable marker fails closed for two live callers; bytes preserved, 0 submits."""
    root = _fresh("r7")
    rig = make_rig(root, owner=SAME_OWNER)
    broken = Path(root) / "reservations" / f"{rig.rec['instance_id']}__att-broken.reservation.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b'{"schema": "mf.comfy.prompt_reservation/1", "key": "trunc')
    broken_sha = _sha(broken)
    callers = [make_rig(root, owner=SAME_OWNER, transport=rig.transport, write_epoch=False),
               make_rig(root, owner="other-owner", transport=rig.transport, write_epoch=False)]
    results: list = []
    barrier = threading.Barrier(2)

    def call(index, caller):
        barrier.wait(30)
        results.append(_outcome(caller, _spec(SAME_ATTEMPT if index == 0 else "att-broken")))

    threads = [threading.Thread(target=call, args=(i, c), name=f"r27-read-error-{i}")
               for i, c in enumerate(callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    disk = _disk_state(root)
    broken_measured = next((m for m in disk["markers"]
                            if str(m["path"]).endswith("att-broken.reservation.json")), {})
    checks: list = []
    _chk(checks, "two_live_callers_joined", 2, len(results))
    for index, res in enumerate(results):
        _chk(checks, f"caller{index}.typed_refusal", "MF_COMFY_CORRUPT_RESERVATION",
             res.get("error") or "")
        _chk(checks, f"caller{index}.no_phantom_success", None, res.get("status"))
        _chk(checks, f"caller{index}.published_nothing", [], res.get("published"))
        _chk(checks, f"caller{index}.never_submitted", 0, res.get("submit_count"))
    _chk(checks, "ZERO_submits_total", 0, rig.transport.submit_calls)
    _chk(checks, "unreadable_marker_preserved_byte_identical", broken_sha, _sha(broken))
    _chk(checks, "marker_not_quarantined_or_deleted", True, broken.exists())
    # The measuring helper must SURFACE the unreadable record instead of raising
    # on it or masking it as `{}`: the row is about an unreadable marker, so the
    # read error itself is part of the measured disk state.
    _chk(checks, "unreadable_marker_surfaced_not_masked", True,
         bool((broken_measured.get("record") or {}).get("read_error")))
    _chk(checks, "unreadable_marker_read_error_names_json", True,
         "JSONDecodeError" in str((broken_measured.get("record") or {}).get("read_error")))
    _chk(checks, "no_artifact_staged", [], [s["name"] for s in disk["staged"]])
    _chk(checks, "no_receipt_written", 0, len(disk["receipts"]))
    return _row("R27-7", "read_error_is_not_absence",
                {"rendezvous_point": "two live callers released from a barrier; both fail closed "
                                     "before the gate, so no gate rendezvous is needed",
                 "callers": results, "unreadable_marker_sha256": broken_sha,
                 "unreadable_marker_bytes": broken.read_bytes().decode("utf-8", "replace"),
                 "submit_calls": rig.transport.submit_calls, "disk": disk}, checks)


# ---------------------------------------------------------------------- ROW 8
def _row_independent_attempt_control() -> dict:
    """CONTROL: a genuinely independent new attempt still POSTs twice (no over-locking)."""
    root = _fresh("r8")
    race = _race_gate(root, spec_a=_spec("att-A"), spec_b=_spec("att-B"),
                      history={"pid-1": history_success("pid-1", "first.png"),
                               "pid-2": history_success("pid-2", "duplicate.png")})
    disk, a_side, b_side = race["disk"], race["A"], race["B"]
    checks: list = []
    _chk(checks, "rendezvous_reached", True, race["rendezvous_reached"])
    _chk(checks, "threads_joined", True, race["threads_joined"])
    _chk(checks, "A_completed_before_B_entered_gate", True, race["a_completed_before_b_gate"])
    _chk(checks, "A_status_validated", "validated", a_side.get("status"))
    _chk(checks, "B_status_validated", "validated", b_side.get("status"))
    _chk(checks, "TWO_posts_total", 2, race["submit_calls"])
    _chk(checks, "B_not_adopted", False, bool(b_side.get("adopted")))
    _chk(checks, "A_published_first_png", ["first.png"], a_side.get("published"))
    _chk(checks, "B_published_own_artifact", ["duplicate.png"], b_side.get("published"))
    _chk(checks, "B_reported_other_attempts_receipt", True,
         "terminal_record_other_attempt" in b_side.get("events", []))
    _chk(checks, "B_reenumerated_union_inside_gate", 2,
         b_side.get("events", []).count("durable_union_enumerated"))
    _chk(checks, "two_receipts_distinct_attempts", ["att-A", "att-B"],
         sorted(r["record"].get("attempt_id") for r in disk["receipts"]))
    _chk(checks, "both_artifacts_on_disk", 2, len(disk["staged"]))
    _chk(checks, "no_marker_left_on_disk", 0, len(disk["markers"]))
    return _row("R27-8", "independent_attempt_control_two_posts", race, checks)


# ------------------------------------------------------------ frozen test rows
def test_r27_same_attempt_race_a_success_b_waits_single_post():
    row = _row_a_success_b_waits()
    assert row["ok"], _explain(row)


def test_r27_same_attempt_race_a_failure_b_refuses():
    row = _row_a_failure_b_refuses()
    assert row["ok"], _explain(row)


def test_r27_unresolved_inflight_second_caller_refused():
    row = _row_unresolved_inflight_second_caller()
    assert row["ok"], _explain(row)


def test_r27_valid_exact_replay_reuses_receipt():
    row = _row_valid_exact_replay()
    assert row["ok"], _explain(row)


def test_r27_different_workflow_input_owner_fail_closed():
    row = _row_identity_variants_fail_closed()
    assert row["ok"], _explain(row)


def test_r27_true_orphan_requeues_once():
    row = _row_true_orphan_requeues_once()
    assert row["ok"], _explain(row)


def test_r27_read_error_is_not_absence():
    row = _row_read_error_is_not_absence()
    assert row["ok"], _explain(row)


def test_r27_independent_attempt_control_two_posts():
    row = _row_independent_attempt_control()
    assert row["ok"], _explain(row)


ROWS = {
    "test_r27_same_attempt_race_a_success_b_waits_single_post": _row_a_success_b_waits,
    "test_r27_same_attempt_race_a_failure_b_refuses": _row_a_failure_b_refuses,
    "test_r27_unresolved_inflight_second_caller_refused": _row_unresolved_inflight_second_caller,
    "test_r27_valid_exact_replay_reuses_receipt": _row_valid_exact_replay,
    "test_r27_different_workflow_input_owner_fail_closed": _row_identity_variants_fail_closed,
    "test_r27_true_orphan_requeues_once": _row_true_orphan_requeues_once,
    "test_r27_read_error_is_not_absence": _row_read_error_is_not_absence,
    "test_r27_independent_attempt_control_two_posts": _row_independent_attempt_control,
}


def run_all() -> dict:
    rows = {name: builder() for name, builder in ROWS.items()}
    return {"rows": rows,
            "checks_passed": sum(r["passed"] for r in rows.values()),
            "checks_total": sum(r["total"] for r in rows.values()),
            "rows_ok": sum(1 for r in rows.values() if r["ok"]),
            "rows_total": len(rows),
            "all_ok": all(r["ok"] for r in rows.values())}
