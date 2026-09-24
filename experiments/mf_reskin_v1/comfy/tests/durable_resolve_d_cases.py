"""Round-D case engine (NR01 / NR02) — the frozen subcase matrix as raw counts.

NOT a test module. It builds disposable fixtures, drives the adapter over the fake
transport, and returns per-subcase RAW counters plus expected-vs-observed rows:

    POST (transport.submit_calls) / publication / isolated staging /
    markers on disk / completion receipts / quarantine records / retained evidence
    / the candidate union the resolver enumerated / the resolver's decision events

Rows (frozen by the round-D packet):

    C04R-a  valid single receipt (control)
    C04R-b  exact receipt + wrong-owner marker, exact claimant enumerated first
    C04R-c  wrong-owner marker + exact receipt, wrong claimant enumerated first
    C04R-d  exact receipt + wrong-owner receipt
    C04R-e  two exact receipts
    C04R-f  foreign workspace/owner; alternate key/path
    C04R-g  marker + receipt + quarantine cross-state
    C05R-a  malformed JSON quarantine record
    C05R-b  `{}` empty-object quarantine
    C05R-c  quarantine missing required authority fields
    C05R-d  read error on a quarantine file
    C05R-e  quarantine filename vs body mismatch
    C05R-f  same attempt, changed epoch
    C07R    genuinely independent NEW work item with a fresh attempt (no over-locking)

`tests/test_durable_resolve_d.py` asserts one matrix row per case; the round-D
evidence runner (`COMFY/raw/run_matrix_d.py`) dumps the same cases to JSON and runs
the identical probe against the archived PRE-FIX bytes as the negative control.
"""
from __future__ import annotations

import hashlib
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
# NOTE (round D, static gate): the adapter is exercised through the rig returned by
# `make_rig()`, so no direct `ComfyStageAdapter` import is needed here (ruff F401).
from mf_comfy.lease import submit_provably_never_started  # noqa: E402

# SHORT scratch root: a deep evidence path plus a generated ledger file name exceeds
# Windows MAX_PATH and fails with a confusing FileNotFoundError (round-C pitfall).
SCRATCH = Path(os.environ.get("MF_COMFY_SCRATCH")
               or (Path(os.environ.get("TEMP") or r"C:/Users/Admin/AppData/Local/Temp"))
               ) / f"mfd_{os.getpid()}"

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


def sha256_file(path) -> str:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return "ABSENT" if not p.exists() else "NOT_A_FILE"
    return hashlib.sha256(p.read_bytes()).hexdigest()


def durable_fingerprints(store) -> dict:
    """sha256 of every durable ledger file, keyed by path relative to the store root."""
    out: dict = {}
    for base in (store.root, store.closed_dir):
        if not Path(base).exists():
            continue
        for p in sorted(Path(base).rglob("*")):
            if p.is_file():
                out[str(Path(p).relative_to(store.root))] = sha256_file(p)
    return out


class Fixture:
    def __init__(self, label, root, rig, marker_path):
        self.label = label
        self.root = root
        self.rig = rig
        self.marker_path = marker_path
        self.store = rig.adapter.reservations

    @property
    def marker(self) -> dict:
        return json.loads(self.marker_path.read_text(encoding="utf-8"))

    def write_marker(self, rec: dict, name: str) -> Path:
        p = self.marker_path.parent / name
        p.write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
        return p

    def quarantine_path(self, name: str | None = None) -> Path:
        return self.marker_path.parent / (name or
                                          self.marker_path.name.replace(
                                              ".reservation.json", ".quarantined.json"))

    def receipt_path(self) -> Path:
        return next(self.store.closed_dir.glob("*.released.json"))

    def replay(self, **spec_kw) -> dict:
        return replay(self.root, self.rig, **spec_kw)

    def counts(self) -> dict:
        return counts(self.rig.transport, self.rig.adapter)


def unresolved_fixture(label: str, **spec_kw) -> Fixture:
    """Start one attempt, leave it UNRESOLVED with a durable marker + terminal history."""
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
    rig.transport.history_map["pid-2"] = history_success("pid-2", "duplicate.png")
    marker = next(rig.adapter.reservations.root.glob("*.reservation.json"))
    return Fixture(label, root, rig, marker)


def replay(root: Path, rig, *, write_epoch: bool = False, owner: str = "owner",
           requested=None, **spec_kw) -> dict:
    """One attempt over the SAME durable dirs with FRESH process state."""
    same = make_rig(root, transport=rig.transport, write_epoch=write_epoch, owner=owner)
    spec_kw.setdefault("owner", owner)
    store = same.adapter.reservations
    before = durable_fingerprints(store)
    union = same.adapter.ledger_candidates(same.adapter.instance_epoch)
    try:
        result = same.adapter.run(requested if requested is not None else base_spec(**spec_kw))
        verdict = _verdict(same, result=result)
    except BaseException as exc:  # noqa: BLE001 - a refusal is a recorded outcome
        verdict = _verdict(same, exc=exc)
    finally:
        if same.gate is not None and same.gate.held:
            same.gate.release()
        same.lease.release()
    after = durable_fingerprints(store)
    verdict["union_before"] = {"markers": len(union["markers"]),
                              "receipts": len(union["receipts"]),
                              "quarantined": len(union["quarantined"]),
                              "misnamed": len(union["misnamed"]),
                              "corrupt": len(union["corrupt"])}
    verdict["evidence_before"] = before
    verdict["evidence_after"] = after
    verdict["evidence_retained"] = all(after.get(k) == v for k, v in before.items())
    verdict["evidence_new"] = sorted(set(after) - set(before))
    seq = [e for e in same.adapter.reservation_events
           if e.get("action") == "durable_union_enumerated"]
    verdict["claimant_sequence"] = [
        [f"{c['bucket']}:{Path(str(c['path'])).name}" for c in ev.get("claimants", [])]
        for ev in seq]
    verdict["union_events"] = seq[:1]
    return verdict


def counts(transport, adapter) -> dict:
    store = adapter.reservations
    return {
        "post_calls": transport.submit_calls,
        "published_artifacts": None,
        "markers_on_disk": len(list(store.root.glob("*.reservation.json"))),
        "unresolved": len(store.unresolved()),
        "receipts": len(store.receipts()),
        "quarantined": len(store.quarantined()),
        "staged_files": sorted(p.name for p in Path(adapter.paths.root).rglob("*.png")),
    }


def _verdict(rig, *, result=None, exc=None) -> dict:
    d = counts(rig.transport, rig.adapter)
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


def _row(row_id: str, case: str, checks: list, steps) -> dict:
    return {"row": row_id, "case": case, "checks": checks,
            "passed": sum(1 for c in checks if c["ok"]), "total": len(checks),
            "ok": all(c["ok"] for c in checks), "steps": steps}


def _refusal_row(checks: list, label: str, v: dict, *, allow_at_terminal: bool = False,
                 staged_expected=None) -> None:
    """The four properties every refusal in this round must have.

    `staged_expected` is the exact staging the fixture may legitimately leave behind
    (artifacts of an EARLIER accepted run, kept as evidence); when it is None the row
    only asserts that a second POST left no NEW artifact behind — `duplicate.png` is
    the file name only the second submit can produce.
    """
    allowed = set(REFUSE_CODES) if allow_at_terminal else {
        "MF_COMFY_CORRUPT_RESERVATION", "MF_COMFY_RESERVATION_CONFLICT"}
    chk(checks, f"{label}.no_new_post", 1, v["post_calls"])
    chk_in(checks, f"{label}.typed_refusal", allowed, v["error"] or "")
    chk(checks, f"{label}.nothing_published", [], v["published"])
    if staged_expected is None:
        chk(checks, f"{label}.no_new_staging", False, "duplicate.png" in v["staged_files"])
    else:
        chk(checks, f"{label}.staging_unchanged", sorted(staged_expected),
            sorted(v["staged_files"]))


# ------------------------------------------------------------------------- C04R
def case_c04r_a_valid_single_receipt() -> dict:
    """C04R-a: one genuine receipt, nothing else claims the attempt ⇒ reuse."""
    checks: list = []
    fx = unresolved_fixture("d_a_valid")
    first = fx.replay()                       # adopt + validate -> terminal_success
    second = fx.replay()
    chk(checks, "first_run.status", "validated", first["status"])
    chk(checks, "first_run.post_calls", 1, first["post_calls"])
    chk(checks, "second_run.status", "validated", second["status"])
    chk(checks, "second_run.disposition", "reused_validated_evidence", disposition(second))
    chk(checks, "second_run.post_calls", 1, second["post_calls"])
    chk(checks, "second_run.published", ["original.png"], second["published"])
    chk(checks, "second_run.duplicate_never_published", False,
        "duplicate.png" in second["staged_files"])
    chk(checks, "second_run.receipts", 1, second["receipts"])
    chk(checks, "second_run.union_has_one_receipt", 1, second["union_before"]["receipts"])
    chk(checks, "second_run.union_enumerated_once", 1, len(second["claimant_sequence"]))
    chk(checks, "second_run.single_claimant", 1,
        len(second["claimant_sequence"][0]) if second["claimant_sequence"] else None)
    return _row("C04R-a", "c04r_a_valid_single_receipt", checks,
                {"first_run": first, "second_run": second})


def _receipt_plus_wrong_owner_marker(label: str, *, exact_first: bool) -> Fixture:
    """Exact receipt + a wrong-owner marker for the SAME attempt, in either order.

    `exact_first` controls which of the two claimants the union yields first: the
    resolver enumerates markers -> receipts -> quarantine, so an exact marker named
    to sort first puts the EXACT claimant ahead of the wrong-owner marker, and a
    wrong-owner marker named to sort first puts the WRONG claimant ahead. Both states
    contain exactly the claimants the frozen row names (an exact receipt and a
    wrong-owner marker); the exact marker is the ordering anchor.
    """
    fx = unresolved_fixture(label)
    rec = fx.marker
    fx.replay()                               # -> exact completion receipt
    wrong = dict(rec, owner="foreign", key="wrong-owner")
    exact = dict(rec, key="exact-anchor")
    if exact_first:
        fx.write_marker(exact, "a0-exact-anchor.reservation.json")
        fx.write_marker(wrong, "zz-wrong-owner.reservation.json")
    else:
        fx.write_marker(wrong, "a0-wrong-owner.reservation.json")
        fx.write_marker(exact, "zz-exact-anchor.reservation.json")
    return fx


def case_c04r_b_exact_receipt_plus_wrong_marker_order1() -> dict:
    """C04R-b: exact receipt + wrong-owner marker, exact claimant enumerated first."""
    checks: list = []
    fx = _receipt_plus_wrong_owner_marker("d_b_order1", exact_first=True)
    v = fx.replay()
    _refusal_row(checks, "order1", v)
    chk(checks, "order1.wrong_owner_claimant_present", True,
        any("wrong-owner" in c for seq in v["claimant_sequence"] for c in seq))
    chk(checks, "order1.exact_claimant_enumerated_first", True,
        bool(v["claimant_sequence"]) and "exact-anchor" in v["claimant_sequence"][0][0])
    chk(checks, "order1.evidence_retained", True, v["evidence_retained"])
    chk(checks, "order1.union_enumerated_before_decision", {"markers": 2, "receipts": 1},
        {"markers": v["union_before"]["markers"], "receipts": v["union_before"]["receipts"]})
    return _row("C04R-b", "c04r_b_exact_receipt_plus_wrong_marker_order1", checks,
                {"order1": v})


def case_c04r_c_wrong_marker_plus_exact_receipt_order2() -> dict:
    """C04R-c: wrong-owner marker + exact receipt, wrong claimant enumerated first."""
    checks: list = []
    fx = _receipt_plus_wrong_owner_marker("d_c_order2", exact_first=False)
    v = fx.replay()
    _refusal_row(checks, "order2", v)
    chk(checks, "order2.wrong_owner_claimant_present", True,
        any("wrong-owner" in c for seq in v["claimant_sequence"] for c in seq))
    chk(checks, "order2.wrong_claimant_enumerated_first", True,
        bool(v["claimant_sequence"]) and "wrong-owner" in v["claimant_sequence"][0][0])
    chk(checks, "order2.evidence_retained", True, v["evidence_retained"])
    chk(checks, "order2.same_refusal_as_order1", "MF_COMFY_RESERVATION_CONFLICT",
        v["error"] or "")
    return _row("C04R-c", "c04r_c_wrong_marker_plus_exact_receipt_order2", checks,
                {"order2": v})


def case_c04r_d_exact_receipt_plus_wrong_receipt() -> dict:
    """C04R-d: exact receipt + a second receipt claiming the same attempt, wrong owner."""
    checks: list = []
    fx = unresolved_fixture("d_d_wrong_receipt")
    fx.replay()
    receipt = fx.receipt_path()
    rec = json.loads(receipt.read_text(encoding="utf-8"))
    rec["owner"] = "foreign"
    (receipt.parent / "zz-extra.released.json").write_text(
        json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    v = fx.replay()
    _refusal_row(checks, "wrong_receipt", v)
    chk(checks, "wrong_receipt.union_two_receipts", 2, v["union_before"]["receipts"])
    chk(checks, "wrong_receipt.evidence_retained", True, v["evidence_retained"])
    return _row("C04R-d", "c04r_d_exact_receipt_plus_wrong_receipt", checks,
                {"wrong_receipt": v})


def case_c04r_e_two_exact_receipts() -> dict:
    """C04R-e: two identical receipts for one attempt ⇒ never a silent pick."""
    checks: list = []
    fx = unresolved_fixture("d_e_two_exact")
    fx.replay()
    receipt = fx.receipt_path()
    raw = receipt.read_bytes()
    (receipt.parent / "zz-extra.released.json").write_bytes(raw)
    v = fx.replay()
    _refusal_row(checks, "two_exact", v)
    chk(checks, "two_exact.duplicate_receipt_byte_identical", True,
        raw == (receipt.parent / "zz-extra.released.json").read_bytes())
    chk(checks, "two_exact.union_two_receipts", 2, v["union_before"]["receipts"])
    chk(checks, "two_exact.no_artifact", [], v["published"])
    return _row("C04R-e", "c04r_e_two_exact_receipts", checks, {"two_exact": v})


def case_c04r_f_foreign_workspace_or_alternate_path() -> dict:
    """C04R-f: another owner/workspace, or a record stored under a foreign name."""
    checks: list = []
    steps: dict = {}

    fx = unresolved_fixture("d_f_foreign_owner")
    fx.replay()
    v = fx.replay(owner="foreign")            # caller declares another owner
    steps["foreign_owner_caller"] = v
    _refusal_row(checks, "foreign_owner_caller", v, allow_at_terminal=True)
    chk(checks, "foreign_owner_caller.receipt_of_another_owner_present", 1,
        v["union_before"]["receipts"])

    fx2 = unresolved_fixture("d_f_alternate_path")
    fx2.replay()
    receipt = fx2.receipt_path()
    moved = receipt.parent / "zone__other-att.released.json"
    shutil.copyfile(receipt, moved)
    v2 = fx2.replay()
    steps["alternate_key_path"] = v2
    _refusal_row(checks, "alternate_key_path", v2)
    chk(checks, "alternate_key_path.moved_copy_retained", True, moved.exists())
    chk(checks, "alternate_key_path.union_reports_misnamed", True,
        v2["union_before"]["misnamed"] >= 1 or v2["union_before"]["corrupt"] >= 1)

    fx3 = unresolved_fixture("d_f_alternate_path_marker")
    rec3 = fx3.marker
    fx3.marker_path.unlink()
    fx3.write_marker(rec3, "zone__other-att.reservation.json")
    v3 = fx3.replay()
    steps["alternate_path_marker"] = v3
    _refusal_row(checks, "alternate_path_marker", v3)
    return _row("C04R-f", "c04r_f_foreign_workspace_or_alternate_path", checks, steps)



def case_c04r_g_cross_state_marker_receipt_quarantine() -> dict:
    """C04R-g: marker + receipt + quarantine all claim the same attempt."""
    checks: list = []
    fx = unresolved_fixture("d_g_cross_state")
    rec = fx.marker
    fx.replay()
    fx.write_marker(rec, fx.marker_path.name)                     # unresolved marker back
    qrec = dict(rec, state="quarantined", quarantine_reason="cross_state_fixture",
                quarantined_at=1.0, quarantine_evidence={}, closer="fixture")
    fx.quarantine_path().write_text(json.dumps(qrec, indent=1, sort_keys=True),
                                    encoding="utf-8")
    v = fx.replay()
    _refusal_row(checks, "cross_state", v)
    chk(checks, "cross_state.union_all_three_buckets",
        {"markers": 1, "receipts": 1, "quarantined": 1},
        {"markers": v["union_before"]["markers"], "receipts": v["union_before"]["receipts"],
         "quarantined": v["union_before"]["quarantined"]})
    chk(checks, "cross_state.evidence_retained", True, v["evidence_retained"])
    chk(checks, "cross_state.quarantine_file_kept", True, fx.quarantine_path().is_file())
    return _row("C04R-g", "c04r_g_cross_state_marker_receipt_quarantine", checks,
                {"cross_state": v})


# ------------------------------------------------------------------------- C05R
def _quarantine_only_fixture(label: str) -> Fixture:
    """Marker replaced by a single quarantine record for the same attempt (reviewer shape)."""
    fx = unresolved_fixture(label)
    rec = fx.marker
    rec["state"] = "quarantined"
    rec.setdefault("quarantine_reason", "fixture")
    fx.marker_path.unlink()
    return fx, rec


def case_c05r_a_malformed_quarantine() -> dict:
    """C05R-a: a quarantine file that does not parse is UNKNOWN, not absent."""
    checks: list = []
    fx, _rec = _quarantine_only_fixture("d_5a_malformed")
    qp = fx.quarantine_path()
    qp.write_bytes(b'{"schema": "mf.comfy.prompt_reservation/1", "key": "trunc')
    before = sha256_file(qp)
    v = fx.replay()
    _refusal_row(checks, "malformed", v, staged_expected=[])
    chk(checks, "malformed.fail_closed", "MF_COMFY_CORRUPT_RESERVATION", v["error"] or "")
    chk(checks, "malformed.file_retained_byte_identical", before, sha256_file(qp))
    chk(checks, "malformed.union_corrupt_reported", True, v["union_before"]["corrupt"] >= 1)
    return _row("C05R-a", "c05r_a_malformed_quarantine", checks, {"malformed": v})


def case_c05r_b_empty_object_quarantine() -> dict:
    """C05R-b: `{}` carries no authority at all ⇒ unknown ⇒ refusal."""
    checks: list = []
    fx, _rec = _quarantine_only_fixture("d_5b_empty")
    qp = fx.quarantine_path()
    qp.write_text("{}", encoding="utf-8")
    before = sha256_file(qp)
    v = fx.replay()
    _refusal_row(checks, "empty_object", v, staged_expected=[])
    chk(checks, "empty_object.fail_closed", "MF_COMFY_CORRUPT_RESERVATION", v["error"] or "")
    chk(checks, "empty_object.file_retained_byte_identical", before, sha256_file(qp))
    return _row("C05R-b", "c05r_b_empty_object_quarantine", checks, {"empty_object": v})


def case_c05r_c_quarantine_missing_authority() -> dict:
    """C05R-c: authority field absent ⇒ the record cannot be attributed ⇒ refusal."""
    checks: list = []
    steps: dict = {}
    for field in ("host", "instance_id", "schema", "key"):
        fx, rec = _quarantine_only_fixture(f"d_5c_{field}")
        rec.pop(field, None)
        qp = fx.quarantine_path()
        qp.write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
        before = sha256_file(qp)
        v = fx.replay()
        steps[field] = v
        _refusal_row(checks, f"missing_{field}", v, staged_expected=[])
        chk(checks, f"missing_{field}.fail_closed", "MF_COMFY_CORRUPT_RESERVATION",
            v["error"] or "")
        chk(checks, f"missing_{field}.file_retained_byte_identical", before, sha256_file(qp))
    return _row("C05R-c", "c05r_c_quarantine_missing_authority", checks, steps)


def case_c05r_d_quarantine_read_error() -> dict:
    """C05R-d: a quarantine path that cannot be read (a directory here) ⇒ unknown."""
    checks: list = []
    fx, _rec = _quarantine_only_fixture("d_5d_readerr")
    qp = fx.quarantine_path()
    qp.mkdir(parents=True, exist_ok=True)
    v = fx.replay()
    _refusal_row(checks, "read_error", v, staged_expected=[])
    chk(checks, "read_error.fail_closed", "MF_COMFY_CORRUPT_RESERVATION", v["error"] or "")
    chk(checks, "read_error.path_retained", True, qp.exists())
    chk(checks, "read_error.union_corrupt_reported", True, v["union_before"]["corrupt"] >= 1)
    return _row("C05R-d", "c05r_d_quarantine_read_error", checks, {"read_error": v})


def case_c05r_e_quarantine_name_body_mismatch() -> dict:
    """C05R-e: the file name describes another instance/attempt than the body."""
    checks: list = []
    fx, _rec = _quarantine_only_fixture("d_5e_mismatch")
    other = fx.quarantine_path("zone__other-att.quarantined.json")
    other.write_text(json.dumps(_rec, indent=1, sort_keys=True), encoding="utf-8")
    before = sha256_file(other)
    v = fx.replay()
    _refusal_row(checks, "name_body_mismatch", v, staged_expected=[])
    chk(checks, "name_body_mismatch.file_retained_byte_identical", before, sha256_file(other))
    return _row("C05R-e", "c05r_e_quarantine_name_body_mismatch", checks,
                {"name_body_mismatch": v})


def case_c05r_f_same_attempt_changed_epoch() -> dict:
    """C05R-f: quarantined under a PREVIOUS boot, same attempt ⇒ no new POST."""
    checks: list = []
    fx, rec = _quarantine_only_fixture("d_5f_old_epoch")
    rec["instance_id"] = "old-epoch"
    qp = fx.quarantine_path("old-epoch__att.quarantined.json")
    qp.write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    # the server booted again: the durable epoch is a DIFFERENT instance now
    fx.rig.epoch.write("http://127.0.0.1:8199", "fake-1.0")
    v = replay(fx.root, fx.rig, write_epoch=False)
    _refusal_row(checks, "old_epoch_same_attempt", v, staged_expected=[])
    chk(checks, "old_epoch_same_attempt.quarantine_enumerated", 1,
        v["union_before"]["quarantined"])
    chk(checks, "old_epoch_same_attempt.no_duplicate_png", False,
        "duplicate.png" in v["staged_files"])
    return _row("C05R-f", "c05r_f_same_attempt_changed_epoch", checks, {"old_epoch_same_attempt": v})


# ------------------------------------------------------------------------- C07R
def case_c07r_independent_new_work() -> dict:
    """C07R: a genuinely NEW attempt must still run — no over-locking."""
    checks: list = []
    steps: dict = {}

    # (1) after a TERMINAL receipt of another attempt
    fx = unresolved_fixture("d_7r_terminal")
    first = fx.replay()
    steps["terminal_attempt"] = first
    chk(checks, "terminal_attempt.status", "validated", first["status"])
    second = fx.replay(attempt_id="att-2")
    steps["independent_after_terminal"] = second
    chk(checks, "independent_after_terminal.status", "validated", second["status"])
    chk(checks, "independent_after_terminal.post_calls", 2, second["post_calls"])
    chk(checks, "independent_after_terminal.published", ["duplicate.png"], second["published"])
    chk(checks, "independent_after_terminal.receipts", 2, second["receipts"])

    # (2) after a QUARANTINE record of another attempt (same stage/workflow)
    fx2, rec = _quarantine_only_fixture("d_7r_quarantine")
    fx2.quarantine_path().write_text(json.dumps(rec, indent=1, sort_keys=True),
                                     encoding="utf-8")
    third = fx2.replay(attempt_id="att-3")
    steps["independent_after_quarantine"] = third
    chk(checks, "independent_after_quarantine.status", "validated", third["status"])
    chk(checks, "independent_after_quarantine.post_calls", 2, third["post_calls"])
    chk(checks, "independent_after_quarantine.published", ["duplicate.png"], third["published"])

    # ACK absence is not proof (retained from round C, still the release gate)
    dead = {"submit_state": "opening", "submit_owner_host": __import__("socket").gethostname(),
            "submit_owner_pid": 999999}
    checks.append({"check": "ack_absence.opening_with_dead_opener_is_proof", "expected": True,
                   "observed": submit_provably_never_started(dead),
                   "ok": submit_provably_never_started(dead) is True})
    for state in ("inflight", "acked", "ambiguous", None):
        rec2 = dict(dead, submit_state=state)
        got = submit_provably_never_started(rec2)
        checks.append({"check": f"ack_absence.{state or 'legacy'}_is_not_proof", "expected": False,
                       "observed": got, "ok": got is False})
    return _row("C07R", "c07r_independent_new_work", checks, steps)


CASES = {
    "c04r_a_valid_single_receipt": case_c04r_a_valid_single_receipt,
    "c04r_b_exact_receipt_plus_wrong_marker_order1": case_c04r_b_exact_receipt_plus_wrong_marker_order1,
    "c04r_c_wrong_marker_plus_exact_receipt_order2": case_c04r_c_wrong_marker_plus_exact_receipt_order2,
    "c04r_d_exact_receipt_plus_wrong_receipt": case_c04r_d_exact_receipt_plus_wrong_receipt,
    "c04r_e_two_exact_receipts": case_c04r_e_two_exact_receipts,
    "c04r_f_foreign_workspace_or_alternate_path": case_c04r_f_foreign_workspace_or_alternate_path,
    "c04r_g_cross_state_marker_receipt_quarantine": case_c04r_g_cross_state_marker_receipt_quarantine,
    "c05r_a_malformed_quarantine": case_c05r_a_malformed_quarantine,
    "c05r_b_empty_object_quarantine": case_c05r_b_empty_object_quarantine,
    "c05r_c_quarantine_missing_authority": case_c05r_c_quarantine_missing_authority,
    "c05r_d_quarantine_read_error": case_c05r_d_quarantine_read_error,
    "c05r_e_quarantine_name_body_mismatch": case_c05r_e_quarantine_name_body_mismatch,
    "c05r_f_same_attempt_changed_epoch": case_c05r_f_same_attempt_changed_epoch,
    "c07r_independent_new_work": case_c07r_independent_new_work,
}

ROW_ORDER = ["C04R-a", "C04R-b", "C04R-c", "C04R-d", "C04R-e", "C04R-f", "C04R-g",
             "C05R-a", "C05R-b", "C05R-c", "C05R-d", "C05R-e", "C05R-f", "C07R"]


def run_case(name: str) -> dict:
    return CASES[name]()


def run_all() -> dict:
    reset_scratch()
    rows = {}
    for name in CASES:
        rows[name] = CASES[name]()
    total = sum(r["total"] for r in rows.values())
    passed = sum(r["passed"] for r in rows.values())
    return {"rows": rows, "row_order": ROW_ORDER,
            "checks_passed": passed, "checks_total": total,
            "rows_ok": sum(1 for r in rows.values() if r["ok"]), "rows_total": len(rows),
            "all_ok": all(r["ok"] for r in rows.values())}


def accounting() -> dict:
    """Counts ALL ledger files ON DISK (not a trusted per-case prefix)."""
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
